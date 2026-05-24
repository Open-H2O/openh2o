from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render


@login_required
def periods_list(request):
    return HttpResponse("periods_list stub")


@login_required
def period_detail(request, pk):
    return HttpResponse("period_detail stub")


@login_required
def period_create(request):
    return HttpResponse("period_create stub")


@login_required
def period_finalize(request, pk):
    return HttpResponse("period_finalize stub")


@login_required
def accounts_list(request):
    return HttpResponse("accounts_list stub")


@login_required
def account_detail(request, pk):
    return HttpResponse("account_detail stub")


@login_required
def account_create(request):
    return HttpResponse("account_create stub")


@login_required
def assign_parcel(request, pk):
    return HttpResponse("assign_parcel stub")


@login_required
def remove_parcel(request, pk, wap_pk):
    return HttpResponse("remove_parcel stub")


@login_required
def parcel_search_for_assignment(request, pk):
    return HttpResponse("parcel_search_for_assignment stub")


@login_required
def allocations_list(request):
    return HttpResponse("allocations_list stub")


@login_required
def allocation_create(request):
    return HttpResponse("allocation_create stub")
